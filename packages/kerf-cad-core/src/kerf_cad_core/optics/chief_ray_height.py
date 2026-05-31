"""
kerf_cad_core.optics.chief_ray_height — paraxial chief-ray height trace through
a sequential optical system.

Public API
----------
ChiefRayHeightReport
    Dataclass holding per-surface chief-ray heights and derived quantities.

trace_chief_ray(lens_system_dict, field_angle_deg, stop_surface_idx)
    Trace the paraxial chief ray from an object at the given field angle through
    a sequential lens system; report the chief-ray height at each surface.

Theory (Welford "Aberrations of Optical Systems" §3 / Mahajan "Optical Imaging
and Aberrations" §2)
---------------------------------------------------------------------
The *chief ray* (also called the *principal ray*) is the ray that originates at
an off-axis object point and passes through the *centre* of the aperture stop.
In the paraxial model it is characterised by:

    h_stop = 0    (height at aperture-stop surface)
    u_obj  = field angle in object space (approx. tan θ for finite-conjugate)

For a system with the stop at infinity-conjugate (object at infinity), the
chief ray enters with angle u_obj = tan(θ_field) in air.

Algorithm (paraxial superposition, Welford 1986 §3.7)
------------------------------------------------------
1.  Two auxiliary paraxial rays are traced to locate the chief-ray initial slope
    that forces h_stop = 0:

    Ray A: height H_obj at first surface (object height transported to first
           surface by object_distance propagation), slope 0.
    Ray B: height h_B = object_distance (paraxial unit-slope ray), slope 1.

    Combined slope α satisfies:
        h_A_stop + α · h_B_stop = 0   →   α = −h_A_stop / h_B_stop

2.  The chief ray is then:
        h0 = H_obj + object_distance · α
        u0 = α

3.  Trace h0, u0 through all surfaces using the nu-form paraxial refraction:

        n_prime · u_prime = n · u − h · c · (n_prime − n)
        h_{j+1} = h_j + t_j · u_prime_j

4.  Collect h_j (height at each surface) and u_prime_j (angle after each
    surface) for the report.

5.  The image height equals the chief-ray height propagated to the paraxial
    image plane (i.e., where the marginal ray crosses the axis).

Object-at-infinity handling
~~~~~~~~~~~~~~~~~~~~~~~~~~~
For a collimated (infinite-conjugate) object the paraxial chief ray is
launched from height 0 at the first surface with slope:

    u_chief = tan(θ_field)   (exact tangent; small-angle paraxial valid for
                              θ_field < ~15° in most designs)

When object_distance_mm is set to a very large value (default 1e9 mm ≈ ∞)
the algorithm automatically recovers the infinite-conjugate case.

Chief-ray height at the aperture stop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
By construction the chief ray passes through h = 0 at the aperture-stop
surface.  The traced height at stop_surface_idx is numerically near zero
(< 1 pm for well-conditioned systems).  This is reported verbatim (not
forced to zero) so users can see any floating-point residual.

Image height
~~~~~~~~~~~~
Image height = height of the chief ray propagated to the paraxial image
plane.  For a thin lens with stop at the lens, this equals f · tan(θ).

HONEST CAVEATS
--------------
  * PARAXIAL ONLY — heights and angles are first-order approximations.
    Exact chief-ray heights at large field angles or large NA differ from
    the paraxial values (exact ray requires Newton-Raphson conic intersect).
  * APERTURE STOP POSITION MUST BE SUPPLIED — there is no automatic stop
    position determination in this module; the caller must pass
    stop_surface_idx (see optics_compute_entrance_pupil for stop location).
  * ROTATIONALLY SYMMETRIC SYSTEMS ONLY — the paraxial trace is scalar
    (meridional plane only); skew-ray / off-axis-stop systems are not
    modelled.
  * IMAGE HEIGHT formula is correct for Gaussian optics; distortion
    (non-paraxial departure from f·tan θ) is not included here.
  * Telecentric object-space condition (stop at front focal plane) yields
    u_obj ≈ 0 and the chief ray enters parallel to the axis — the
    magnification is then insensitive to object-distance errors.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §3 (paraxial chief ray), §3.7 (stop and pupil positions),
    §4.4 (chief-ray angle and telecentricity).
Mahajan, V.N. -- "Optical Imaging and Aberrations, Part I", SPIE Press, 2011,
    §2 (paraxial optics, pupil and stop).
Smith, W.J. -- "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008,
    §5 (chief ray, stop, aperture).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §6.6 (stops, pupils, chief ray, field of view).

Units: lengths in mm, angles in degrees at API boundary (radians internally).

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
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False,
           nonneg: bool = False) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    if nonneg and v < 0.0:
        return f"{name} must be >= 0, got {v}"
    return None


def _paraxial_trace_all(
    surfaces: list[dict],
    h0: float,
    u0: float,
    n_object: float = 1.0,
) -> tuple[list[float], list[float], float, float]:
    """
    Trace a paraxial ray through all surfaces.

    Returns
    -------
    (heights, angles_after, h_final, u_final)
    heights[j]      : ray height at surface j BEFORE refraction (mm)
    angles_after[j] : ray slope AFTER refraction at surface j (rad)
    h_final         : ray height after transfer from last surface
    u_final         : ray slope after last surface
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

    return heights, angles_after, h, u


def _solve_chief_ray_ic(
    surfaces: list[dict],
    field_angle_deg: float,
    stop_surface_idx: int,
    object_distance_mm: float,
    n_object: float,
) -> tuple[float, float]:
    """
    Solve for the chief-ray initial conditions (h0, u0) at the first surface.

    Uses paraxial superposition (Welford 1986 §3.7):

        Ray A: (H_obj, 0) → h_A_stop
        Ray B: (obj_dist, 1) → h_B_stop
        α = u_obj = -h_A_stop / h_B_stop

    For infinite conjugate (object_distance_mm very large), the chief ray
    enters with u0 = tan(θ) and h0 = 0.

    Returns (h0, u0) — the chief ray height and slope at the first surface.
    """
    theta_rad = math.radians(float(field_angle_deg))
    H_obj = 1.0  # object height used for normalisation (rescaled below)

    # ── Infinite-conjugate shortcut ──────────────────────────────────────────
    # When object_distance_mm is very large, the chief-ray height at the first
    # surface is approximately 0 for any reasonable object height, and the
    # chief-ray slope u0 = tan(θ_field) regardless of field height H_obj.
    # The superposition still works (Ray B height at stop → obj_dist, which
    # dominates), but numerical precision degrades.  For obj_dist > 1e6 mm
    # we use the closed-form result directly.
    if object_distance_mm > 1e6:
        u0 = math.tan(theta_rad)
        # Propagate the chief ray from just before the first surface to the stop
        # to verify it passes through h=0.  For stop at first surface, h0=0.
        # For stop at another surface, we need to find h0 such that h_stop=0.
        if stop_surface_idx == 0:
            return 0.0, u0

        # Finite distance from first surface to stop:
        # trace ray (h0, u0) through surfaces 0..stop_surface_idx-1;
        # solve for the h0 offset that zeroes h_stop.
        # By linearity: h_stop(h0) = h_A_stop + h0 * contribution_per_unit_h0.
        # Ray with h0=0: heights_0[stop_surface_idx] = h_0_stop
        heights_0, _, _, _ = _paraxial_trace_all(
            surfaces, 0.0, u0, n_object
        )
        h_0_stop = heights_0[stop_surface_idx]

        # Ray with h0=1, same u0: heights_1[stop_surface_idx] = h_1_stop
        heights_1, _, _, _ = _paraxial_trace_all(
            surfaces, 1.0, u0, n_object
        )
        h_1_stop = heights_1[stop_surface_idx]

        dh = h_1_stop - h_0_stop
        if abs(dh) < 1e-15:
            # Degenerate (flat slab?): h0 unchanged
            return 0.0, u0

        # h_0_stop + alpha * dh = 0
        alpha = -h_0_stop / dh
        h0 = alpha
        return h0, u0

    # ── Finite-conjugate superposition ──────────────────────────────────────
    # Object point at (height=H_obj, z=-object_distance_mm)
    # Chief ray must pass through h=0 at aperture stop.

    # Ray A: object height=H_obj, object slope=0
    #        At first surface: h0_A = H_obj, u0_A = 0
    h0_A = H_obj
    heights_A, _, _, _ = _paraxial_trace_all(surfaces, h0_A, 0.0, n_object)
    h_A_stop = heights_A[stop_surface_idx]

    # Ray B: object height=0, object slope=1
    #        At first surface: h0_B = object_distance_mm, u0_B = 1
    h0_B = float(object_distance_mm)
    heights_B, _, _, _ = _paraxial_trace_all(surfaces, h0_B, 1.0, n_object)
    h_B_stop = heights_B[stop_surface_idx]

    if abs(h_B_stop) < 1e-15:
        # Degenerate: use tan(θ) as fallback
        u_obj = math.tan(theta_rad)
    else:
        # α = -h_A_stop / h_B_stop gives the slope coefficient
        # but this is per-unit H_obj; scale by actual field angle
        alpha_unit = -h_A_stop / h_B_stop
        # The actual chief-ray slope is: u0 = field-angle equivalent
        # The object-height H_obj maps to tan(θ) at object distance:
        #   H_obj = object_distance_mm * tan(θ)
        # The normalised α (per unit H_obj) maps to:
        #   u_obj_actual = alpha_unit * H_obj / object_distance_mm... but
        # a cleaner approach: scale H_obj = obj_dist * tan(θ) so that the
        # superposition result gives u_obj = tan(θ).
        H_actual = object_distance_mm * math.tan(theta_rad)
        h_A_actual_stop = h_A_stop * (H_actual / H_obj)  # linearity
        if abs(h_B_stop) < 1e-15:
            u_obj = math.tan(theta_rad)
        else:
            u_obj = -h_A_actual_stop / h_B_stop

    # Chief-ray height at first surface
    H_actual = object_distance_mm * math.tan(theta_rad)
    h0 = H_actual + object_distance_mm * u_obj
    u0 = u_obj

    return h0, u0


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChiefRayHeightReport:
    """
    Result of a paraxial chief-ray height trace through a sequential optical
    system.

    Attributes
    ----------
    per_surface_heights : list[dict]
        Per-surface chief-ray data.  Each dict contains:
          surface_idx   : int   — surface index (0-based)
          ray_height_mm : float — chief-ray height at this surface (mm)
          ray_angle_deg : float — chief-ray angle AFTER refraction at this
                                   surface (degrees)
    image_height_mm : float
        Chief-ray height at the paraxial image plane (mm).
        Equals f · tan(θ_field) for a thin lens at infinity conjugate.
    magnification : float
        Paraxial lateral magnification = image_height / object_height.
        Only meaningful for finite-conjugate traces.
    stop_surface_idx : int
        Index of the aperture stop surface supplied by the caller.
    chief_ray_at_stop_mm : float
        Chief-ray height at the aperture stop (should be ≈ 0).
    object_angle_deg : float
        Chief-ray angle in object space (degrees).
    image_angle_deg : float
        Chief-ray angle in image space (degrees, after last surface).
    honest_caveat : str
        Scope limitation statement.

    References
    ----------
    Welford (1986) §3 / §3.7; Mahajan (2011) §2; Smith (2008) §5.
    """

    per_surface_heights: list[dict]
    image_height_mm: float
    magnification: float
    stop_surface_idx: int
    chief_ray_at_stop_mm: float
    object_angle_deg: float
    image_angle_deg: float
    honest_caveat: str = (
        "PARAXIAL ONLY: first-order chief-ray heights. "
        "Aperture stop position must be supplied by caller. "
        "Rotationally symmetric systems only. "
        "Image height = f·tan(θ) (no distortion). "
        "Ref: Welford (1986) §3; Mahajan (2011) §2."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "per_surface_heights": self.per_surface_heights,
            "image_height_mm": self.image_height_mm,
            "magnification": self.magnification,
            "stop_surface_idx": self.stop_surface_idx,
            "chief_ray_at_stop_mm": self.chief_ray_at_stop_mm,
            "object_angle_deg": self.object_angle_deg,
            "image_angle_deg": self.image_angle_deg,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def trace_chief_ray(
    lens_system_dict: dict,
    field_angle_deg: float,
    stop_surface_idx: int,
) -> "ChiefRayHeightReport | dict":
    """
    Trace the paraxial chief ray through a sequential optical system.

    The chief ray originates from an object point at field angle
    ``field_angle_deg`` (the half-field angle in object space) and passes
    through the *centre* (h = 0) of the aperture stop at surface
    ``stop_surface_idx``.

    Parameters
    ----------
    lens_system_dict : dict
        Optical system specification.  Required key:
          surfaces : list[dict]
            Ordered list of surface dicts, each with:
              c  : curvature 1/R (mm⁻¹).  0 = flat.
              t  : axial thickness to next surface vertex (mm).  Last: 0.
              n  : refractive index of medium AFTER this surface (≥ 1.0).
              k  : conic constant (optional; not used for paraxial trace).
        Optional keys:
          n_object : float
            Refractive index of object space (default 1.0 = air).
          object_distance_mm : float
            Axial distance from object plane to first surface vertex (mm).
            Default 1e9 (effectively infinity — collimated input).
          object_height_mm : float
            Off-axis object height (mm) used only for finite-conjugate
            magnification calculation.  Default 1.0.

    field_angle_deg : float
        Half-field angle in object space (degrees).  The chief ray enters
        the system at this angle relative to the optical axis.
        Range: [0, 90).  0° = on-axis (chief ray height = 0 everywhere).

    stop_surface_idx : int
        Index (0-based) of the aperture stop surface in the surfaces list.
        The chief ray is constrained to have h = 0 at this surface.
        Must satisfy 0 ≤ stop_surface_idx < len(surfaces).

    Returns
    -------
    ChiefRayHeightReport
        Dataclass with per-surface heights, image height, magnification,
        and other derived quantities.
    dict {"ok": False, "reason": ...}
        On any validation error.

    Notes
    -----
    * For stop at surface 0 (first surface), the chief ray enters with
      h_0 = 0 and slope = tan(θ_field) in air.
    * For an infinite-conjugate system, image_height ≈ EFL × tan(θ_field).
    * Paraxial result deviates from exact ray trace for large field angles
      (> 15°) or fast lenses (f/# < 2).

    References
    ----------
    Welford (1986) §3; Mahajan (2011) §2; Smith (2008) §5.
    """
    # ---- Validate lens_system_dict -----------------------------------------
    if not isinstance(lens_system_dict, dict):
        return _err("lens_system_dict must be a dict")

    surfaces = lens_system_dict.get("surfaces")
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("lens_system_dict.surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        e = _validate_surface(s, idx)
        if e:
            return _err(e)

    n_surf = len(surfaces)

    # ---- Validate scalar params --------------------------------------------
    e = _guard("field_angle_deg", field_angle_deg)
    if e:
        return _err(e)
    field_angle_deg = float(field_angle_deg)
    if not (0.0 <= field_angle_deg < 90.0):
        return _err("field_angle_deg must be in [0, 90)")

    if not isinstance(stop_surface_idx, int):
        try:
            stop_surface_idx = int(stop_surface_idx)
        except (TypeError, ValueError):
            return _err("stop_surface_idx must be an integer")
    if not (0 <= stop_surface_idx < n_surf):
        return _err(
            f"stop_surface_idx {stop_surface_idx} out of range "
            f"[0, {n_surf - 1}]"
        )

    n_object = float(lens_system_dict.get("n_object", 1.0))
    if n_object < 1.0:
        return _err("n_object must be >= 1.0")

    object_distance_mm = float(
        lens_system_dict.get("object_distance_mm", 1e9)
    )
    e = _guard("object_distance_mm", object_distance_mm, positive=True)
    if e:
        return _err(e)

    object_height_mm = float(lens_system_dict.get("object_height_mm", 1.0))

    # ---- Solve chief-ray initial conditions --------------------------------
    h0, u0 = _solve_chief_ray_ic(
        surfaces,
        field_angle_deg,
        stop_surface_idx,
        object_distance_mm,
        n_object,
    )

    # ---- Trace the chief ray through all surfaces --------------------------
    heights, angles_after, h_final, u_final = _paraxial_trace_all(
        surfaces, h0, u0, n_object
    )

    # ---- Paraxial image distance (from marginal ray h=1, u=0) --------------
    # Trace marginal ray to find the image plane
    marg_heights, marg_angles, marg_h_final, marg_u_final = (
        _paraxial_trace_all(surfaces, 1.0, 0.0, n_object)
    )
    if abs(marg_u_final) < 1e-18:
        image_dist = math.inf
    else:
        image_dist = -marg_h_final / marg_u_final

    # ---- Image height = chief ray propagated to image plane ----------------
    if math.isfinite(image_dist):
        image_height_mm = h_final + image_dist * u_final
    else:
        image_height_mm = h_final

    # ---- Magnification (finite conjugate only) -----------------------------
    if object_distance_mm < 1e6 and abs(object_height_mm) > 1e-12:
        # Scale image height by object height normalisation
        # object_height_mm here is notional; the chief-ray height at object
        # maps to field angle: H_obj = object_distance_mm * tan(theta)
        H_obj_paraxial = object_distance_mm * math.tan(
            math.radians(field_angle_deg)
        )
        if abs(H_obj_paraxial) > 1e-15:
            magnification = image_height_mm / H_obj_paraxial
        else:
            magnification = 1.0
    else:
        magnification = float("nan")

    # ---- Per-surface report ------------------------------------------------
    per_surface = []
    for j, (h_j, u_after_j) in enumerate(zip(heights, angles_after)):
        per_surface.append({
            "surface_idx": j,
            "ray_height_mm": h_j,
            "ray_angle_deg": math.degrees(u_after_j),
        })

    chief_ray_at_stop = heights[stop_surface_idx]
    object_angle_deg_out = math.degrees(u0)
    image_angle_deg_out = math.degrees(u_final)

    return ChiefRayHeightReport(
        per_surface_heights=per_surface,
        image_height_mm=image_height_mm,
        magnification=magnification,
        stop_surface_idx=stop_surface_idx,
        chief_ray_at_stop_mm=chief_ray_at_stop,
        object_angle_deg=object_angle_deg_out,
        image_angle_deg=image_angle_deg_out,
    )
