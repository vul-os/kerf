"""
kerf_cad_core.optics.exit_pupil — exit pupil position and size.

The exit pupil is the image of the aperture stop as seen from image space
(looking back through the rear lens elements).  Its position (longitudinal
distance from the last surface vertex) and semi-diameter determine the angle
at which image-space rays converge to each focal point.

Algorithm (Welford 1986 §4.4 / Hecht §6.6)
--------------------------------------------
Given a lens stack described by surface dicts and the index of the surface
that acts as the aperture stop:

1.  Construct the *rear sub-stack*: surfaces stop_surface_index+1 … N−1.
    If stop_surface_index == N−1 (last surface), the rear sub-stack is empty
    and the exit pupil coincides with the stop at z=0.

2.  Trace TWO paraxial rays forward from the aperture stop through the rear
    elements.

    Ray 1 (marginal edge ray):
        h1 = stop_radius_mm,  u1 = 0  (parallel to axis at stop edge)

    Ray 2 (axial position ray for pupil location):
        h2 = 0,  nu2 = 1  (nu = n * u = 1; unit slope in normalised form)
        => u2 = 1 / n_stop  at the stop plane

    Both rays start at the stop vertex and are transferred forward by
    t[stop_surface_index] (the gap from the stop to the first rear surface),
    then refracted at each subsequent rear surface j:

        nu_prime = n_in * u - h * c_j * (n_out - n_in)     [nu-form, Welford §3.3]
        u_prime  = nu_prime / n_out
        h_{j+1}  = h_j + t_j * u_prime_j

    (t_j = 0 for the last surface by convention; ray heights at the last surface
    are the final h1_last, h2_last, u1_last, u2_last.)

3.  After the forward trace, both rays are in image space at the last surface
    vertex.  Exit pupil position from the last surface:

        position_z_mm = -h2_last / u2_last      [from Welford §4.4 eq. 4.4.5]

    Positive = real exit pupil behind the last surface (in image space).
    Negative = virtual exit pupil inside the barrel.

    Note: this is NOT the axis crossing of Ray 1 (which gives the back focal
    point, not the image of the stop).  Ray 2 (h=0, nu=1 at stop) encodes the
    B-element of the rear-group ABCD matrix; the exit pupil position follows
    from -B / D (Welford §4.4).

4.  Exit pupil radius = height of Ray 1 at the exit pupil plane z_ep:

        radius_mm = |h1_last + position_z_mm x u1_last|

    This is the image of the stop edge through the rear group.

5.  Magnification = radius_mm / stop_radius.

Depth bar
----------
*  Stop at last surface (stop_surface_index = N-1): trivial case, exit pupil
   at z=0, diameter = stop diameter, magnification = 1.  (Thin-lens identity;
   Hecht §6.6.)

*  Thin lens with stop at the front surface, t=0 to rear surface: exit pupil
   at z=0, radius = stop_radius, magnification = 1.  (Stop and rear surface
   coincide; no rear elements.)

*  BK7 biconvex (R=50 mm, n=1.5168, t=5 mm), stop at first surface:
   exit pupil is virtual (z < 0 from last surface), slightly outside the lens.

*  Telescope (objective f_obj=100 mm, eyepiece f_eye=25 mm, afocal):
   stop at the objective -> exit pupil (Ramsden disk) at z = f_obj * f_eye /
   (f_obj - f_eye + separation) behind the eyepiece.  For f_obj=100, f_eye=25,
   sep=125 mm: z_ep = 31.25 mm, radius = stop_r x f_eye/f_obj = 1.25 mm,
   magnification = 0.25 = 1 / (telescope angular magnification).
   (Hecht §6.6 Ramsden disk.)

*  Welford §4.4 oracle (rear glass-air surface, n=1.5168, R=-50 mm, 5 mm behind stop):
   z_ep approx -3.41 mm (virtual, inside glass), radius approx 5.18 mm, m approx 1.04.

Honest flags
-------------
* PARAXIAL ONLY.  Real exit pupil requires tracing a paraxial chief ray from
  image space back through the rear group to the stop.  The paraxial result
  agrees with the real pupil only for small field angles and near-axis points.

* The stop is modelled as a thin plane (zero thickness).

* Paraxial approximation degrades for fast systems (f/# < 2) or wide-field
  designs.

* ENTRANCE PUPIL COMPUTATION IS SEPARATE (entrance_pupil.py).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §4.4 (entrance and exit pupils, paraxial pupil imaging).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §6.6 (stops, pupils, windows; Ramsden disk).

Units: lengths in mm, angles in radians.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    _guard,
    _paraxial_refract,
    _paraxial_transfer,
    _validate_surface,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExitPupilReport:
    """Result of compute_exit_pupil.

    Attributes
    ----------
    position_z_mm : float
        Longitudinal position of the exit pupil along the optical axis,
        measured from the *last surface vertex*.
        Positive = real exit pupil behind the last surface (in image space).
        Zero = coincides with the last surface.
        Negative = virtual exit pupil inside the lens barrel (in front of
        the last surface, as seen from image space).

    radius_mm : float
        Semi-diameter (half-diameter) of the exit pupil in mm.

    diameter_mm : float
        Full diameter = 2 x radius_mm.

    magnification : float
        Transverse magnification of the rear group mapping stop to exit pupil:
            m = exit_pupil_radius / stop_radius
        For a stop at the last surface: m = 1.0.
        m < 1 -> pupil is smaller than the physical stop (e.g. telescope Ramsden disk).
        m > 1 -> pupil is larger.
    """

    position_z_mm: float
    radius_mm: float
    diameter_mm: float
    magnification: float

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "position_z_mm": self.position_z_mm,
            "radius_mm": self.radius_mm,
            "diameter_mm": self.diameter_mm,
            "magnification": self.magnification,
            "honest_flag": (
                "PARAXIAL ONLY.  Entrance pupil computation is a separate function. "
                "Stop assumed thin (zero thickness).  Paraxial approximation "
                "degrades for fast (f/# < 2) or wide-field systems. "
                "Ref: Welford 1986 §4.4; Hecht §6.6."
            ),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_exit_pupil(
    surfaces: list[dict],
    stop_diameter_mm: float,
    stop_surface_index: int = 0,
    n_object: float = 1.0,
) -> "ExitPupilReport | dict":
    """
    Compute the paraxial exit pupil position and size for a lens stack.

    The exit pupil is the image of the aperture stop as seen from image space,
    formed by all lens elements behind the stop (Welford 1986 §4.4; Hecht §6.6).

    Parameters
    ----------
    surfaces : list of dicts
        Ordered list of surface dicts (same format as trace_lens_stack):
          c  : curvature 1/R (mm^-1).  0 = flat.
          t  : thickness to next surface (mm).  Last surface: 0.
          n  : refractive index of medium AFTER this surface.
          k  : conic constant (optional; unused for paraxial trace).
    stop_diameter_mm : float
        Full diameter of the aperture stop (mm).  Must be > 0.
    stop_surface_index : int
        Index (0-based) of the surface at whose vertex the aperture stop
        sits.  Default 0 = stop at the first surface.
    n_object : float
        Refractive index of the object-space medium (default 1.0 = air).
        Used to build the full medium sequence.

    Returns
    -------
    ExitPupilReport  on success.
    dict {"ok": False, "reason": ...}  on error.

    Algorithm (Welford 1986 §4.4)
    -----------------------------
    Traces TWO paraxial rays forward from the stop through the rear sub-stack:

    Ray 1:  h = stop_radius,  nu = 0  at stop (marginal edge ray parallel to axis).
    Ray 2:  h = 0,  nu = 1  at stop  (axial ray with unit normalised slope).

    After the forward trace through all rear surfaces:
      position_z_mm = -h2_last / u2_last    (axis crossing of ray 2 from last surface)
      radius_mm     = |h1_last + z_ep x u1_last|  (ray 1 height at exit pupil plane)
      magnification = radius_mm / stop_radius

    This correctly gives the IMAGE of the stop through the rear group, not merely
    the back focal point (which would be -h1_last/u1_last, only equal to z_ep when
    the stop is at the front focal plane of the rear group).

    Ref: Welford (1986) §4.4 eq. 4.4.5; Hecht §6.6 (Ramsden disk).
    """
    # ---- Validate inputs ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    e = _guard("stop_diameter_mm", stop_diameter_mm, positive=True)
    if e:
        return _err(e)

    e = _guard("n_object", n_object)
    if e:
        return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    n_surfs = len(surfaces)
    if not isinstance(stop_surface_index, int):
        try:
            stop_surface_index = int(stop_surface_index)
        except (TypeError, ValueError):
            return _err("stop_surface_index must be an integer")

    if stop_surface_index < 0 or stop_surface_index >= n_surfs:
        return _err(
            f"stop_surface_index {stop_surface_index} out of range "
            f"[0, {n_surfs - 1}]"
        )

    stop_radius = float(stop_diameter_mm) / 2.0

    # ---- Medium sequence (forward direction) --------------------------------
    # n_seq[0]   = n_object       (medium before surface 0)
    # n_seq[j+1] = n after surface j  for j = 0 ... N-1
    n_seq: list[float] = [float(n_object)] + [float(s["n"]) for s in surfaces]

    # ---- Trivial case: stop at last surface ---------------------------------
    if stop_surface_index == n_surfs - 1:
        return ExitPupilReport(
            position_z_mm=0.0,
            radius_mm=stop_radius,
            diameter_mm=2.0 * stop_radius,
            magnification=1.0,
        )

    # ---- Medium at the stop and rear sub-stack ------------------------------
    # The stop sits at the vertex of surfaces[stop_surface_index].
    # The medium immediately to the RIGHT of the stop = n_seq[stop_surface_index + 1].
    n_stop_medium = n_seq[stop_surface_index + 1]

    # The gap from the stop plane to the first rear surface:
    t_stop_to_first = float(surfaces[stop_surface_index]["t"])

    # Rear sub-stack: surfaces[stop_surface_index+1 .. N-1]
    rear_start = stop_surface_index + 1
    rear = surfaces[rear_start:]
    n_rear = len(rear)   # >= 1 (not in trivial case)

    # ---- Forward paraxial trace: two rays -----------------------------------
    # Ray 1: marginal edge ray — starts at stop edge, parallel to axis.
    #   h1 = stop_radius, nu1 = 0  =>  u1 = 0
    # Ray 2: axial pupil-location ray — starts at stop center, unit nu.
    #   h2 = 0, nu2 = 1  =>  u2 = 1 / n_stop_medium
    h1 = stop_radius
    u1 = 0.0
    h2 = 0.0
    u2 = 1.0 / n_stop_medium if n_stop_medium > 0 else 1.0

    # Transfer from stop plane to first rear surface:
    if t_stop_to_first != 0.0:
        h1 = _paraxial_transfer(h1, u1, t_stop_to_first)
        h2 = _paraxial_transfer(h2, u2, t_stop_to_first)

    # Process each rear surface left to right:
    n_cur = n_stop_medium
    for k, surf in enumerate(rear):
        c_k = float(surf["c"])
        t_k = float(surf["t"])
        n_out = n_seq[rear_start + k + 1]

        # Refract both rays at rear surface k:
        u1 = _paraxial_refract(h1, u1, n_cur, n_out, c_k)
        u2 = _paraxial_refract(h2, u2, n_cur, n_out, c_k)
        n_cur = n_out

        # Transfer to the next rear surface (not for the last one):
        if k < n_rear - 1 and t_k != 0.0:
            h1 = _paraxial_transfer(h1, u1, t_k)
            h2 = _paraxial_transfer(h2, u2, t_k)

    # After the loop: h1, u1, h2, u2 are all in image space at the last surface vertex.

    # ---- Exit pupil position (Welford §4.4 eq. 4.4.5) ----------------------
    # Ray 2 encodes the B-element of the rear-group ABCD matrix (B = h2_last since h2_init=0,
    # nu2_init=1).  The axis crossing of Ray 2 gives the exit pupil position:
    #   z_ep = -h2 / u2   [from the last surface toward image space]
    if abs(u2) < 1e-18:
        position_z_mm = math.inf   # rear group is afocal — exit pupil at infinity
    else:
        position_z_mm = -h2 / u2

    # ---- Exit pupil radius --------------------------------------------------
    # Ray 1 started at (h=stop_r, u=0). At the exit pupil plane z_ep from the last surface:
    #   h1(z_ep) = h1_last + z_ep * u1_last
    # This height is the transverse distance from axis at the exit pupil plane,
    # i.e. the exit pupil radius (Welford §4.4; Hecht §6.6).
    if math.isfinite(position_z_mm):
        h1_at_ep = h1 + position_z_mm * u1
    else:
        h1_at_ep = 0.0

    pupil_radius_mm = abs(h1_at_ep)

    # Guard against degenerate case (afocal / telecentric rear group):
    if pupil_radius_mm < 1e-15:
        pupil_radius_mm = abs(h1)   # fall back to height at last surface

    magnification = pupil_radius_mm / stop_radius if stop_radius > 0.0 else 1.0

    return ExitPupilReport(
        position_z_mm=position_z_mm,
        radius_mm=pupil_radius_mm,
        diameter_mm=2.0 * pupil_radius_mm,
        magnification=magnification,
    )
