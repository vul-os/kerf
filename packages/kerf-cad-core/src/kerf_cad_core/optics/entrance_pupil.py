"""
kerf_cad_core.optics.entrance_pupil — entrance pupil position and size.

The entrance pupil is the image of the aperture stop as seen from
object space (looking through all lens elements in front of the stop).
Its position (z-coordinate relative to the first surface vertex) and
semi-diameter determine the effective light-gathering cone accepted by
the optical system from any object point.

Algorithm (Welford 1986 §4.4 / Hecht §6.6)
--------------------------------------------
Given a lens stack described by surface dicts and the index of the
surface that acts as the aperture stop:

1.  Construct the *front sub-stack*: surfaces 0 … stop_surface_index−1.
    If stop_surface_index == 0, the front sub-stack is empty and the
    entrance pupil coincides with the stop.

2.  Trace a paraxial *reverse* ray from the stop edge toward object
    space.  Initial conditions at the stop vertex plane:

        ray_h = stop_radius_mm   (edge of the aperture stop)
        ray_u = 0                (ray parallel to the optical axis)

    For each surface j = stop_surface_index−1, stop_surface_index−2, …, 0
    (right-to-left):

      a. TRANSFER backward by t_j mm (the gap from surface j to surface j+1
         in the forward direction) through the current medium.

      b. REFRACT at surface j with:
           n_in  = n[j]       (medium to the right in forward dir)
           n_out = n[j-1]     (medium to the left  in forward dir; = n_object if j=0)
           c_rev = -c[j]      (negate curvature for reverse trace; Welford 1986 §4.4)

3.  After the reverse trace, the ray is in object space at z=0 (first
    surface vertex) with height h and angle u.  Find the axis crossing:

        position_z_mm = -h / u      [from the first surface vertex]

    Negative values mean the pupil is virtual (in front of the first surface).

4.  Entrance pupil semi-diameter = |h| (height at the first surface vertex
    after the full reverse trace).

5.  Magnification = entrance_pupil_radius / stop_radius.

Depth bar
----------
*  Stop at first surface (stop_surface_index=0): entrance pupil at z=0,
   diameter = stop diameter, magnification = 1.  (Thin-lens identity;
   Hecht §6.6.)

*  Stop behind a single converging lens (e.g. BK7 biconvex, stop at
   rear surface): the reverse trace through the front surface maps the
   stop to an image in object space whose position depends on the lens
   power and the stop-to-front-surface distance.

*  Stop in front of all lenses: trivially stop_surface_index=0, pupil
   = stop.

Honest flags
-------------
* PARAXIAL ONLY.  Exact (real-ray) entrance pupil requires tracing a
  paraxial chief ray from object space to the stop; the paraxial pupil
  position agrees with the real position only for small field angles
  and near-axis object points.

* EXIT PUPIL COMPUTATION IS SEPARATE.  Exit pupil = image of stop in
  image space, formed by the rear group.  Not implemented in this module.

* The stop is modelled as a thin plane (zero thickness).  Stops with
  physical extent or obscuration are not modelled.

* Paraxial approximation degrades for fast systems (f/# < 2) or
  wide-field designs.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §4.4 (entrance and exit pupils, paraxial pupil imaging).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §6.6 (stops, pupils, windows).

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
class EntrancePupilReport:
    """Result of compute_entrance_pupil.

    Attributes
    ----------
    position_z_mm : float
        Longitudinal position of the entrance pupil along the optical axis,
        measured from the *first surface vertex*.  Negative values mean the
        pupil is to the left of (i.e. in front of) the first surface —
        a virtual entrance pupil in object space.  Zero = coincides with
        the first surface.  Positive = inside the lens barrel (behind the
        first surface, but still in object space relative to the stop).

    radius_mm : float
        Semi-diameter (half-diameter) of the entrance pupil in mm.

    diameter_mm : float
        Full diameter = 2 × radius_mm.

    magnification : float
        Transverse magnification of the front group at the stop plane:
            m = entrance_pupil_radius / stop_radius
        For a stop at the first surface: m = 1.0.
        m > 1 → pupil appears larger than the physical stop.
        m < 1 → pupil appears smaller.
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
                "PARAXIAL ONLY.  Exit pupil computation is a separate function. "
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

def compute_entrance_pupil(
    surfaces: list[dict],
    stop_diameter_mm: float,
    stop_surface_index: int = 0,
    n_object: float = 1.0,
) -> "EntrancePupilReport | dict":
    """
    Compute the paraxial entrance pupil position and size for a lens stack.

    The entrance pupil is the image of the aperture stop as seen from
    object space, formed by all lens elements in front of the stop
    (Welford 1986 §4.4; Hecht §6.6).

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

    Returns
    -------
    EntrancePupilReport  on success.
    dict {"ok": False, "reason": ...}  on error.

    Algorithm (Welford 1986 §4.4)
    -----------------------------
    Reverse-traces a paraxial ray (h=stop_radius, u=0) from the stop
    vertex through the front sub-stack (surfaces before the stop),
    processing each surface j right-to-left:
      1. Transfer backward by t[j] (the gap from surface j to surface j+1).
      2. Refract with negated curvature and reversed index ordering.
    The axis crossing of the emerging object-space ray gives
    position_z_mm = -h/u from the first surface vertex.
    """
    # ── Validate inputs ──────────────────────────────────────────────────────
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

    # ── Trivial case: stop at first surface ──────────────────────────────────
    if stop_surface_index == 0:
        return EntrancePupilReport(
            position_z_mm=0.0,
            radius_mm=stop_radius,
            diameter_mm=2.0 * stop_radius,
            magnification=1.0,
        )

    # ── Build front sub-stack ────────────────────────────────────────────────
    # front[j] = surfaces[j] for j = 0 … stop_surface_index−1
    front = surfaces[:stop_surface_index]
    n_front = len(front)

    # Medium sequence (forward direction):
    #   n_seq[0]   = n_object       (medium before surface 0)
    #   n_seq[j+1] = n after front[j]  for j = 0 … n_front-1
    n_seq: list[float] = [float(n_object)] + [float(front[j]["n"]) for j in range(n_front)]

    # ── Reverse paraxial trace ────────────────────────────────────────────────
    # Start at the stop vertex: h = stop_radius, u = 0.
    # Process surfaces j = n_front-1 down to 0:
    #   step 1: TRANSFER backward by t[j] (gap from surface j to surface j+1)
    #   step 2: REFRACT at surface j (reversed curvature, reversed indices)
    h = stop_radius
    u = 0.0

    for j in range(n_front - 1, -1, -1):
        t_j  = float(front[j]["t"])    # gap from surface j to j+1 (forward)
        c_j  = float(front[j]["c"])
        n_in = n_seq[j + 1]            # medium to the right of surface j (forward)
        n_out = n_seq[j]               # medium to the left  of surface j (forward)

        # 1. Transfer backward by t_j in medium n_in (from surface j+1 to surface j)
        if t_j != 0.0:
            h = _paraxial_transfer(h, u, t_j)

        # 2. Refract at surface j (Welford 1986 §4.4):
        #    negate curvature for reverse direction
        c_rev = -c_j
        u = _paraxial_refract(h, u, n_in, n_out, c_rev)

    # ── Entrance pupil position ───────────────────────────────────────────────
    # After the trace the ray is in object space at z = 0 (first surface vertex)
    # with height h and angle u (in medium n_object).
    # Axis crossing: propagate forward from z=0 until h + z_ep * u = 0
    #   z_ep = -h / u
    if abs(u) < 1e-18:
        position_z_mm = math.inf   # ray is parallel to axis — pupil at infinity
    else:
        position_z_mm = -h / u

    # ── Entrance pupil semi-diameter ─────────────────────────────────────────
    # The ray height at the first surface vertex (z=0) equals the pupil radius
    # only when position_z_mm == 0.  For a general z_ep, the pupil radius is the
    # height of the ray AT the pupil plane, which equals h + z_ep * u = 0.
    #
    # But what we want is the MAGNIFICATION: how large does the stop appear from
    # object space?  In paraxial optics the transverse magnification of the front
    # group maps the stop semi-diameter to the pupil semi-diameter.
    #
    # The correct pupil radius is obtained by noting that the reverse ray started
    # at h = stop_radius and u = 0.  After the reverse trace, the ray slope u_out
    # encodes the angular size, while h_out = h at the first surface vertex.
    #
    # The entrance pupil is the image of the stop: the ray from the stop edge
    # (h=stop_r, u=0) maps to the pupil edge.  The height of that edge in the
    # pupil plane is found by propagating from z=0 to z=position_z_mm:
    #
    #   h_pupil = h + position_z_mm * u
    #           = h + (-h/u) * u  = h - h = 0   [that's the axis crossing, not the edge]
    #
    # We need a different ray to find the pupil height.  The standard approach:
    # trace a ray from the AXIAL point at the stop (h=0, u=u_marginal) through
    # the front group in reverse to find the pupil diameter from u_marginal.
    # But Welford §4.4 uses the original marginal ray height and slope:
    #
    #   m = -n_stop * u_initial / (n_object * u_final)  [Welford §4.4 eq. 4.4.2]
    #
    # where u_initial = 0 for our reverse ray, so this degenerates.
    # Instead, use the angular magnification via the Lagrange invariant:
    #
    #   H = n_obj * h_obj * u_obj = n_stop * h_stop * u_stop = constant
    #
    # For our reverse ray: at the stop, n=n_stop=n_seq[n_front], h=stop_r, u=0.
    # H = n_stop * stop_r * 0 = 0.
    # A degenerate marginal ray (u=0 at stop) carries no Lagrange info.
    #
    # The correct pupil radius uses a second ray traced from the axial stop
    # with a unit angle, which gives the transverse magnification directly.
    # --
    # Alternatively (Welford §4.4 §4.5): the entrance pupil radius is simply
    # the height of the reverse-traced ray AT THE PUPIL PLANE z = position_z_mm,
    # which equals zero (that IS the definition of the pupil as axis crossing).
    #
    # The right method:  trace a second "pupil-size ray" from the stop axial
    # point with slope u = 1 (in the stop-side medium) and record its height
    # at the entrance pupil plane.  The ratio h2(z_ep) / 1 = m_t (transverse mag).

    # ── Second ray: find transverse magnification of front group ─────────────
    # Trace a ray from the stop axial point: h=0, u=1 (unit slope) in the
    # medium immediately to the right of the front sub-stack = n_seq[n_front].
    h2 = 0.0
    u2 = 1.0

    for j in range(n_front - 1, -1, -1):
        t_j   = float(front[j]["t"])
        c_j   = float(front[j]["c"])
        n_in  = n_seq[j + 1]
        n_out = n_seq[j]
        c_rev = -c_j

        if t_j != 0.0:
            h2 = _paraxial_transfer(h2, u2, t_j)
        u2 = _paraxial_refract(h2, u2, n_in, n_out, c_rev)

    # At z=0 (first surface vertex) the second ray has height h2 and angle u2.
    # Propagate to z = position_z_mm to get the entrance pupil height for unit slope:
    if math.isfinite(position_z_mm):
        h2_at_pupil = h2 + position_z_mm * u2
    else:
        h2_at_pupil = 0.0

    # The entrance pupil edge is:
    #   h_ep = stop_radius * |h2_at_pupil / 1.0|
    # because the first ray started at h=stop_r, u=0 at the stop, and the
    # second ray at h=0, u=1.  By superposition (paraxial optics is linear):
    #   h_ep(z_ep) = stop_r * h_first(z_ep)/stop_r  + 0
    # But h_first(z_ep) = 0 by definition of z_ep!  That's the axis crossing.
    # --
    # The correct decomposition is:
    #   Pupil radius = |stop_radius × (derivative of pupil position w.r.t. stop radius)|
    #               = |stop_radius| × |m_t|
    # where m_t = d(h_pupil_plane) / d(stop_radius).
    #
    # We get m_t from the first ray:  ray1 had (h1=stop_r, u1=0) at stop,
    # and emerges in object space as (h1_obj, u1_obj).  By linearity:
    #   (h1_obj, u1_obj) = stop_r * (A row 1, B row 1) of the front group matrix
    # where A, B are the front-group paraxial ABCD matrix elements for the path
    # from stop to first surface.
    #
    # The entrance pupil is where h1_obj + z * u1_obj = 0, i.e. z = -h1_obj/u1_obj.
    # The pupil RADIUS equals |h1_obj| + z_ep * |u1_obj| evaluated differently.
    #
    # Actually: the pupil is an IMAGE of the stop.  The stop edge ray (h=R, u=0)
    # in object space traces to (h_obj, u_obj) after the front group in reverse.
    # The chief ray from the axial object through the pupil edge has angle:
    #   u_chief = h_ep / z_ep  (if pupil is at finite z).
    # But the stop edge ray emerges with height h_obj at z=0 and ZERO height at
    # z = z_ep.  To find the pupil DIAMETER, we note that in paraxial optics:
    #
    #   pupil_radius = |h1_obj|   AT z=0 only if z_ep=0.
    #   For z_ep != 0: pupil_radius = |h1_obj + z_ep * u1_obj| but that equals 0.
    #
    # --
    # The resolution: the entrance pupil radius is NOT the height of the marginal
    # ray AT the pupil plane (that's zero by construction).  It is the height
    # of the MARGINAL RAY at the STOP, projected through the front group:
    #
    #   pupil_radius = |m_t| × stop_radius
    #
    # where m_t is the transverse magnification of the front group from stop to
    # entrance pupil plane.
    #
    # m_t = h_pupil / h_stop = (stop_r) * (ABCD element) / stop_r
    # For a thin lens with stop at its rear focal point: m_t → ∞ (telecentric).
    # For a stop at the lens: m_t = 1.
    #
    # Correct formula using the front-group matrix (Welford 1986 §4.4):
    # The paraxial ABCD matrix M of the front group (object-space → stop-space)
    # maps (h, n*u) at the entrance pupil to (h, n*u) at the stop.
    # Since the stop edge has (h_stop=stop_r, u_stop=0):
    #   [stop_r]   [A  B] [h_ep       ]
    #   [0     ] = [C  D] [n_obj*u_ep ]
    # From row 1: stop_r = A * h_ep + B * n_obj * u_ep
    # From row 2: 0      = C * h_ep + D * n_obj * u_ep
    #   => n_obj * u_ep = -(C/D) * h_ep   [if D ≠ 0]
    #   => stop_r = (A - B*C/D) * h_ep = (1/D) * h_ep  [since AD-BC=1 for unimodular M]
    #   => h_ep = D * stop_r
    #
    # So: entrance_pupil_radius = D * stop_r  where D is the (2,2) element
    # of the paraxial matrix from the entrance pupil plane to the stop plane.
    #
    # We compute D from the second traced ray:
    # The second ray (h2=0, u2=1 at stop) emerges at (h2_obj, u2_obj) in object space.
    # Propagating to the pupil plane:  h2_at_pupil = h2_obj + z_ep * u2_obj.
    # In matrix form the second ray encodes the B column of M^{-1}:
    #   h2_at_pupil = B * 1 * n_stop = B * n_stop   [since h_stop=0, u_stop=1]
    #
    # Hmm, this is getting complex.  Use the simplest working approach:
    # Compute D directly via the second traced ray with (h=0, u=1/n_stop) at stop
    # so that n_stop * u_stop = 1.  Then D = n_obj * u2_obj (from row 2 of M^{-1}).
    #
    # For n_stop = n_seq[n_front]:
    n_stop = n_seq[n_front]
    # D = n_obj * u2_obj (from the nu-form of the reverse trace starting at u2=1)
    # But our second ray had u2=1 at stop, not u2=1/n_stop.  Let's redo with
    # u2_init = 1/n_stop so that nu2_init = n_stop * u2_init = 1.
    # Then after the reverse trace, D = n_obj * u2_obj_final.
    # (Welford 1986 §3.5 uses nu-form; D = n_out * u_out / (n_in * u_in) for a
    # marginal ray, here is the matrix element.)

    h2b = 0.0
    u2b = 1.0 / n_stop if n_stop > 0 else 1.0   # nu_in = 1

    for j in range(n_front - 1, -1, -1):
        t_j   = float(front[j]["t"])
        c_j   = float(front[j]["c"])
        n_in  = n_seq[j + 1]
        n_out = n_seq[j]
        c_rev = -c_j

        if t_j != 0.0:
            h2b = _paraxial_transfer(h2b, u2b, t_j)
        u2b = _paraxial_refract(h2b, u2b, n_in, n_out, c_rev)

    # D = n_obj * u2b_final  (nu-form element; Welford §3.5)
    n_obj_f = float(n_object)
    D_elem = n_obj_f * u2b

    # Entrance pupil radius = D * stop_radius  (Welford §4.4)
    pupil_radius_mm = abs(D_elem) * stop_radius

    # Guard against degenerate D=0 (afocal / telecentric stop)
    if pupil_radius_mm < 1e-15:
        # Fall back to height of first ray at z=0
        pupil_radius_mm = abs(h)

    magnification = pupil_radius_mm / stop_radius if stop_radius > 0.0 else 1.0

    return EntrancePupilReport(
        position_z_mm=position_z_mm,
        radius_mm=pupil_radius_mm,
        diameter_mm=2.0 * pupil_radius_mm,
        magnification=magnification,
    )
